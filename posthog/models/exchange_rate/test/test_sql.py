import os

import pytest

from posthog.models.exchange_rate.sql import HISTORICAL_EXCHANGE_RATE_DICTIONARY


def test_historical_dictionary_loads_real_data():
    rates_dict = HISTORICAL_EXCHANGE_RATE_DICTIONARY()

    assert rates_dict
    assert "2024-12-31" in rates_dict
    assert rates_dict["2024-12-31"]["EUR"] > 0


def test_historical_dictionary_raises_actionable_error_when_csv_missing(monkeypatch):
    def missing(path):
        return False

    monkeypatch.setattr(os.path, "exists", missing)

    with pytest.raises(FileNotFoundError, match="Exchange rate data file not found"):
        HISTORICAL_EXCHANGE_RATE_DICTIONARY()
