// Jest's CLI only sets NODE_ENV=test when it is unset. When tests are launched
// from an environment where NODE_ENV or DEBUG is already set (IDE test runners,
// debuggers, flox exports DEBUG=1), `determineNodeEnv()` resolves to dev and
// every config default (DATABASE_URL, PERSONS_DATABASE_URL, CLICKHOUSE_DATABASE,
// CYCLOTRON_DATABASE_URL, ...) points at the real dev databases — which
// destructive test helpers would then wipe. Force the test environment so the
// defaults always resolve to their test_* counterparts. Explicitly exported
// *_DATABASE_URL variables still win; tests/helpers/database-guard.ts catches
// those when they point at a non-test database.
process.env.NODE_ENV = 'test'
