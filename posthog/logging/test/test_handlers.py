from posthog.logging.handlers import extractor


def text_extraction() -> None:
    assert extractor.extract(
        "Processed 1.00 billion rows, 13.79 GB (47.13 million rows/s., 650.03 MB/s.) Peak memory usage: 26.16 GiB"
    ) == (
        "Processed $0 billion rows, $1 GB ($2 million rows/s., $3 MB/s.) Peak memory usage: $4 GiB",
        ["1.00", "13.79", "47.13", "650.03", "26.16"],
    )
    assert extractor.extract("from ip: 1.2.3.4; foo") == ("from ip: $0; foo", ["1.2.3.4"])
    assert extractor.extract("2010-06-15 2010-06-15T00:00:00 2010-06-15T00:00:00+00:00 2010-06-15T00:00:00Z") == (
        "$0 $1 $2 $3",
        [
            "2010-06-15",
            "2010-06-15T00:00:00",
            "2010-06-15T00:00:00+00:00",
            "2010-06-15T00:00:00Z",
        ],
    )
    assert extractor.extract("AXES: Using django-axes version 5.9.0") == (
        "AXES: Using django-axes version $0",
        ["5.9.0"],
    )
    assert extractor.extract(
        "Task posthog.tasks.user_identify.identify_task[343d56f0-0ce7-4a3a-b480-9dd8e748fd8f] received"
    ) == (
        "Task $0[$1] received",
        ["posthog.tasks.user_identify.identify_task", "343d56f0-0ce7-4a3a-b480-9dd8e748fd8f"],
    )
