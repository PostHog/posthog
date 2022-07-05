from posthog.tasks.exports.csv_exporter import encode, join_to_csv_line


def test_encoding_a_value() -> None:
    assert encode("tomato") == '"tomato"'
    assert encode('"tomato"') == '"""tomato"""'
    assert encode('{"tomato": ["san marzano", "cherry"]}') == '"{""tomato"": [""san marzano"", ""cherry""]}"'


def test_joining_as_line() -> None:
    assert join_to_csv_line(["potato", "tomato"]) == "potato,tomato\n"
