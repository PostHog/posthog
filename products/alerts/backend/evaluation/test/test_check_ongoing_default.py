from parameterized import parameterized

from posthog.schema import AlertCalculationInterval

from products.alerts.backend.evaluation.validation import should_default_check_ongoing_interval

TRENDS = "TrendsAlertConfig"
FUNNELS = "FunnelsAlertConfig"


def _trends_query(interval="day", non_time_series=False):
    query = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}], "interval": interval}
    if non_time_series:
        query["trendsFilter"] = {"display": "BoldNumber"}
    return query


def _funnels_query(interval="day", viz="trends"):
    return {
        "kind": "FunnelsQuery",
        "series": [{"kind": "EventsNode", "event": "a"}, {"kind": "EventsNode", "event": "b"}],
        "interval": interval,
        "funnelsFilter": {"funnelVizType": viz},
    }


def _threshold(upper=100, lower=None):
    bounds = {}
    if upper is not None:
        bounds["upper"] = upper
    if lower is not None:
        bounds["lower"] = lower
    return {"type": "absolute", "bounds": bounds}


ABSOLUTE = {"type": "absolute_value"}
INCREASE = {"type": "relative_increase"}
DECREASE = {"type": "relative_decrease"}


class TestShouldDefaultCheckOngoingInterval:
    @parameterized.expand(
        [
            # cadence finer than a day-grouped insight, valid trends gate → default on
            ("trends day + 15min", _trends_query(), TRENDS, ABSOLUTE, _threshold(), "every_15_minutes", True),
            ("trends day + hourly", _trends_query(), TRENDS, ABSOLUTE, _threshold(), "hourly", True),
            ("trends day + real_time increase", _trends_query(), TRENDS, INCREASE, _threshold(), "real_time", True),
            # cadence not finer than the insight interval → leave default off
            ("trends day + daily", _trends_query(), TRENDS, ABSOLUTE, _threshold(), "daily", False),
            ("trends hour + hourly", _trends_query("hour"), TRENDS, ABSOLUTE, _threshold(), "hourly", False),
            ("trends hour + 15min", _trends_query("hour"), TRENDS, ABSOLUTE, _threshold(), "every_15_minutes", True),
            # ongoing-check gates: needs absolute/increase AND an upper bound
            (
                "trends no upper bound",
                _trends_query(),
                TRENDS,
                ABSOLUTE,
                _threshold(upper=None, lower=5),
                "hourly",
                False,
            ),
            ("trends decrease condition", _trends_query(), TRENDS, DECREASE, _threshold(), "hourly", False),
            (
                "trends non-time-series",
                _trends_query(non_time_series=True),
                TRENDS,
                ABSOLUTE,
                _threshold(),
                "hourly",
                False,
            ),
            # funnels: only time-series (trends) funnels, and only when finer
            ("trends funnel day + 15min", _funnels_query(), FUNNELS, ABSOLUTE, _threshold(), "every_15_minutes", True),
            (
                "steps funnel day + 15min",
                _funnels_query(viz="steps"),
                FUNNELS,
                ABSOLUTE,
                _threshold(),
                "every_15_minutes",
                False,
            ),
            ("trends funnel day + daily", _funnels_query(), FUNNELS, ABSOLUTE, _threshold(), "daily", False),
        ]
    )
    def test_should_default(self, _name, query, config_type, condition, threshold, cadence, expected):
        result = should_default_check_ongoing_interval(
            query=query,
            config={"type": config_type},
            condition=condition,
            threshold_config=threshold,
            calculation_interval=AlertCalculationInterval(cadence),
        )
        assert result is expected

    @parameterized.expand([("hogql config", {"type": "HogQLAlertConfig"}), ("not a dict", None)])
    def test_non_ongoing_config_never_defaults(self, _name, config):
        result = should_default_check_ongoing_interval(
            query=_trends_query(),
            config=config,
            condition=ABSOLUTE,
            threshold_config=_threshold(),
            calculation_interval=AlertCalculationInterval.HOURLY,
        )
        assert result is False
