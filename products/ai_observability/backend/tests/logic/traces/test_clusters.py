from datetime import timedelta

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.clusters import ClusterMemberships

from .rows import T0, cluster_json, make_cluster, make_cluster_run_row

JOB_A = "0192f2a4-5c1e-7000-8000-0000000c1a0a"
JOB_B = "0192f2a4-5c1e-7000-8000-0000000c1a0b"


def test_finds_the_cluster_whose_traces_list_the_trace() -> None:
    row = make_cluster_run_row(
        clusters=cluster_json(make_cluster(0, ["trace-2"]), make_cluster(3, ["trace-1"], title="Billing questions"))
    )

    [membership] = ClusterMemberships.of("trace-1", [row]).clusters

    assert (membership.cluster_id, membership.title, membership.is_outlier, membership.job_name) == (
        3,
        "Billing questions",
        False,
        "Support conversations",
    )


@parameterized.expand(
    [
        ("a longer id", make_cluster(0, ["trace-10"])),
        ("the id in the title", make_cluster(0, ["trace-2"], title="Retries after trace-1 failed")),
    ]
)
def test_a_near_match_is_not_a_membership(_name: str, near: dict[str, object]) -> None:
    assert ClusterMemberships.of("trace-1", [make_cluster_run_row(clusters=cluster_json(near))]).clusters == ()


def test_keeps_the_newest_scheduled_run_of_each_job() -> None:
    runs = [
        make_cluster_run_row(
            run_id=f"1_trace_20260905_120000_{JOB_A}_retry-tuning",
            job_id=JOB_A,
            job_name="Support conversations",
            timestamp=T0 + timedelta(days=4),
            clusters=cluster_json(make_cluster(9, ["trace-1"])),
        ),
        make_cluster_run_row(
            run_id=f"1_trace_20260903_030000_{JOB_A}",
            job_id=JOB_A,
            job_name="Support conversations",
            timestamp=T0 + timedelta(days=2),
            clusters=cluster_json(make_cluster(4, ["trace-1"])),
        ),
        make_cluster_run_row(
            run_id=f"1_trace_20260902_030000_{JOB_B}",
            job_id=JOB_B,
            job_name="Agent runs",
            timestamp=T0 + timedelta(days=1),
            clusters=cluster_json(make_cluster(1, ["trace-1"])),
        ),
        make_cluster_run_row(
            run_id=f"1_trace_20260904_030000_{JOB_A}",
            job_id=JOB_A,
            job_name="Support conversations",
            timestamp=T0 + timedelta(days=3),
            clusters=cluster_json(make_cluster(2, ["trace-1"])),
        ),
        make_cluster_run_row(
            run_id=f"1_trace_20260902_030000_{JOB_A}",
            job_id=JOB_A,
            job_name="Support conversations",
            timestamp=T0 + timedelta(days=1),
            clusters=cluster_json(make_cluster(0, ["trace-1"])),
        ),
    ]

    clusters = ClusterMemberships.of("trace-1", runs).clusters

    assert [(c.run_id, c.job_id, c.cluster_id) for c in clusters] == [
        (f"1_trace_20260904_030000_{JOB_A}", JOB_A, 2),
        (f"1_trace_20260902_030000_{JOB_B}", JOB_B, 1),
    ]


def test_runs_without_a_job_count_as_one_job() -> None:
    runs = [
        make_cluster_run_row(run_id="1_trace_20260901_030000", job_id="", job_name="", timestamp=T0),
        make_cluster_run_row(
            run_id="1_trace_20260902_030000", job_id="", job_name="", timestamp=T0 + timedelta(days=1)
        ),
        make_cluster_run_row(
            run_id="1_trace_20260903_120000_retry-tuning", job_id="", job_name="", timestamp=T0 + timedelta(days=2)
        ),
    ]

    [membership] = ClusterMemberships.of("trace-1", runs).clusters

    assert (membership.run_id, membership.job_id, membership.job_name) == ("1_trace_20260902_030000", None, None)


def test_outliers_come_after_clusters() -> None:
    runs = [
        make_cluster_run_row(
            run_id=f"1_trace_20260904_030000_{JOB_A}",
            job_id=JOB_A,
            timestamp=T0 + timedelta(days=3),
            clusters=cluster_json(make_cluster(0, ["trace-2"]), make_cluster(-1, ["trace-1"], title="Outliers")),
        ),
        make_cluster_run_row(
            run_id=f"1_trace_20260902_030000_{JOB_B}",
            job_id=JOB_B,
            timestamp=T0 + timedelta(days=1),
            clusters=cluster_json(make_cluster(1, ["trace-1"])),
        ),
    ]

    clusters = ClusterMemberships.of("trace-1", runs).clusters

    assert [(c.cluster_id, c.job_id, c.is_outlier) for c in clusters] == [(1, JOB_B, False), (-1, JOB_A, True)]


@parameterized.expand(
    [
        ("no clusters", None),
        ("not JSON", "[{"),
        ("not a list", '{"cluster_id": 0}'),
        ("a cluster without traces", '[{"cluster_id": 0, "title": "Billing questions"}]'),
        ("a cluster id that is not a number", '[{"cluster_id": "zero", "traces": {"trace-1": {}}}]'),
    ]
)
def test_skips_what_it_cannot_read(_name: str, clusters: str | None) -> None:
    good = make_cluster_run_row(run_id="1_trace_20260901_030000", job_id="", timestamp=T0 + timedelta(hours=1))
    bad = make_cluster_run_row(clusters=clusters)

    assert [m.run_id for m in ClusterMemberships.of("trace-1", [bad, good]).clusters] == ["1_trace_20260901_030000"]


@parameterized.expand([("missing", None), ("empty", "")])
def test_a_run_without_an_id_is_skipped(_name: str, run_id: str | None) -> None:
    assert ClusterMemberships.of("trace-1", [make_cluster_run_row(run_id=run_id)]).clusters == ()


def test_an_empty_title_reads_as_none() -> None:
    row = make_cluster_run_row(clusters=cluster_json(make_cluster(5, ["trace-1"], title="", description="")))

    [membership] = ClusterMemberships.of("trace-1", [row]).clusters

    assert (membership.title, membership.description) == (None, None)
