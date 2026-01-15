import pytest

from products.batch_exports.backend.temporal.pipeline.consumer import _compute_consumers_to_add


@pytest.mark.parametrize(
    "bytes_left,time_left,bytes_consumption_rate,current_consumers,max_consumers,expected,test_description",
    [
        (2000, 10, 100, 1, 10, 1, "double consumers"),
        (500, 10, 100, 2, 10, 0, "current consumers are enough"),
        (10000, 10, 100, 5, 5, 5, "already at max consumers"),
    ],
)
def test_compute_consumers_to_add(
    bytes_left,
    time_left,
    bytes_consumption_rate,
    current_consumers,
    max_consumers,
    expected,
    test_description,
):
    """Test _compute_consumers_to_add function with various scenarios."""
    result = _compute_consumers_to_add(
        bytes_left=bytes_left,
        time_left=time_left,
        bytes_consumption_rate=bytes_consumption_rate,
        current_consumers=current_consumers,
        max_consumers=max_consumers,
    )
    assert result == expected, f"Failed: {test_description}"
