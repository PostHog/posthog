//! Proves the guard gets a pool off a connection whose server stopped accepting writes,
//! without restarting the process. `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`
//! stands in for a demoted Aurora reader: the socket stays healthy, so a liveness check sees
//! nothing, but every write is refused with SQLSTATE 25006.

use common_database::{install_writer_guard, WriterGuard, WriterGuardConfig};
use sqlx::{
    postgres::{PgConnectOptions, PgPoolOptions},
    PgPool, Row,
};

/// One connection, so the second acquire deterministically gets the poisoned one back.
fn single_connection_pool(pool_opts: PgPoolOptions) -> PgPoolOptions {
    pool_opts.min_connections(0).max_connections(1)
}

async fn backend_pid(pool: &PgPool) -> i32 {
    sqlx::query("SELECT pg_backend_pid()")
        .fetch_one(pool)
        .await
        .expect("pid query failed")
        .get(0)
}

async fn transaction_read_only(pool: &PgPool) -> String {
    sqlx::query_scalar("SHOW transaction_read_only")
        .fetch_one(pool)
        .await
        .expect("read-only setting query failed")
}

/// Makes the pool's one connection read-only and returns its backend PID.
async fn poison_the_pooled_connection(pool: &PgPool) -> i32 {
    let mut conn = pool.acquire().await.expect("acquire failed");
    let pid: i32 = sqlx::query("SELECT pg_backend_pid()")
        .fetch_one(&mut *conn)
        .await
        .expect("pid query failed")
        .get(0);
    sqlx::query("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        .execute(&mut *conn)
        .await
        .expect("failed to set the session read-only");
    drop(conn);
    pid
}

#[sqlx::test]
async fn discards_a_read_only_connection_and_reopens_against_the_writer(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let guard = WriterGuard::new(WriterGuardConfig::default());
    let pool = install_writer_guard(single_connection_pool(pool_opts), &guard)
        .connect_with(connect_opts)
        .await
        .expect("connect failed");

    let poisoned_pid = poison_the_pooled_connection(&pool).await;

    // Capped at one connection, so this is either the poisoned one or its replacement.
    assert_ne!(
        backend_pid(&pool).await,
        poisoned_pid,
        "the guard should have discarded the read-only connection and opened a new one"
    );
    assert_eq!(
        transaction_read_only(&pool).await,
        "off",
        "the replacement connection should accept writes"
    );

    pool.close().await;
}

#[sqlx::test]
async fn writes_succeed_again_without_restarting_the_pool(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let guard = WriterGuard::new(WriterGuardConfig::default());
    let pool = install_writer_guard(single_connection_pool(pool_opts), &guard)
        .connect_with(connect_opts)
        .await
        .expect("connect failed");

    sqlx::query("CREATE TABLE guard_probe (id int primary key)")
        .execute(&pool)
        .await
        .expect("setup failed");

    poison_the_pooled_connection(&pool).await;

    // Without the guard this write fails with 25006 until the connection is recycled.
    sqlx::query("INSERT INTO guard_probe (id) VALUES (1)")
        .execute(&pool)
        .await
        .expect("write should succeed on the replacement connection");

    let rows: i64 = sqlx::query_scalar("SELECT count(*) FROM guard_probe")
        .fetch_one(&pool)
        .await
        .expect("count failed");
    assert_eq!(rows, 1);

    pool.close().await;
}

/// The control: without the guard the poisoned connection survives, because its ping passes.
/// Without this the tests above would only prove a healthy database accepts writes.
#[sqlx::test]
async fn without_the_guard_the_poisoned_connection_survives_and_writes_fail(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let pool = single_connection_pool(pool_opts)
        .connect_with(connect_opts)
        .await
        .expect("connect failed");

    sqlx::query("CREATE TABLE guard_probe (id int primary key)")
        .execute(&pool)
        .await
        .expect("setup failed");

    let poisoned_pid = poison_the_pooled_connection(&pool).await;

    assert_eq!(
        backend_pid(&pool).await,
        poisoned_pid,
        "sqlx has no reason to drop a connection that pings fine, so it hands the same one back"
    );
    assert_eq!(transaction_read_only(&pool).await, "on");

    let err = sqlx::query("INSERT INTO guard_probe (id) VALUES (1)")
        .execute(&pool)
        .await
        .expect_err("the write should be refused");
    assert!(
        common_database::is_read_only_error(&err),
        "expected SQLSTATE 25006, got {err:?}"
    );

    pool.close().await;
}

/// The probe replaces sqlx's ping, so the probe is what has to notice a dead socket. Terminating
/// the pooled backend proves the pool still recovers on its own: the probe fails, sqlx discards
/// the connection, and the caller transparently gets a working replacement.
#[sqlx::test]
async fn recovers_when_the_pooled_backend_was_terminated(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let guard = WriterGuard::new(WriterGuardConfig::default());
    let pool = install_writer_guard(single_connection_pool(pool_opts), &guard)
        .connect_with(connect_opts.clone())
        .await
        .expect("connect failed");

    let doomed_pid = backend_pid(&pool).await;

    // A second pool, so killing the pooled backend does not kill the killer. The two-argument
    // form waits for the backend to actually exit, which keeps the assertion below race-free.
    let sidecar = PgPoolOptions::new()
        .max_connections(1)
        .connect_with(connect_opts)
        .await
        .expect("sidecar connect failed");
    let terminated: bool = sqlx::query_scalar("SELECT pg_terminate_backend($1, 5000)")
        .bind(doomed_pid)
        .fetch_one(&sidecar)
        .await
        .expect("terminate failed");
    assert!(terminated, "expected backend {doomed_pid} to exit");

    assert_ne!(
        backend_pid(&pool).await,
        doomed_pid,
        "the probe should have failed on the dead socket and opened a replacement"
    );

    sidecar.close().await;
    pool.close().await;
}

/// The inverse of the poisoning tests, and the one they cannot catch: a probe that discards
/// *every* connection still changes the backend PID and still lets writes succeed, so it passes
/// all of them. In production that is a TCP and TLS handshake per acquire against the writer.
#[sqlx::test]
async fn a_healthy_pool_keeps_one_connection_across_many_acquires(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let guard = WriterGuard::new(WriterGuardConfig::default());
    let pool = install_writer_guard(single_connection_pool(pool_opts), &guard)
        .connect_with(connect_opts)
        .await
        .expect("connect failed");

    let first = backend_pid(&pool).await;
    for i in 0..8 {
        assert_eq!(
            backend_pid(&pool).await,
            first,
            "acquire {i} got a different backend; the guard is churning healthy connections"
        );
    }

    pool.close().await;
}

/// Once the cap is spent the guard stops discarding, so the caller gets the reader and the write
/// is refused. That is the documented behavior for a cluster that accepts no writes: fail fast
/// with a classifiable error and let the alert fire, rather than churn connections.
#[sqlx::test]
async fn a_spent_cap_surfaces_25006_rather_than_churning(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let guard = WriterGuard::new(WriterGuardConfig {
        max_rejections_per_window: 0,
        ..Default::default()
    });
    let pool = install_writer_guard(single_connection_pool(pool_opts), &guard)
        .connect_with(connect_opts)
        .await
        .expect("connect failed");

    sqlx::query("CREATE TABLE guard_probe (id int primary key)")
        .execute(&pool)
        .await
        .expect("setup failed");

    let poisoned_pid = poison_the_pooled_connection(&pool).await;

    let err = sqlx::query("INSERT INTO guard_probe (id) VALUES (1)")
        .execute(&pool)
        .await
        .expect_err("the write should be refused, not silently retried");
    assert!(
        common_database::is_read_only_error(&err),
        "expected SQLSTATE 25006, got {err:?}"
    );
    assert_eq!(
        backend_pid(&pool).await,
        poisoned_pid,
        "a spent cap must keep the connection instead of churning it"
    );

    pool.close().await;
}
