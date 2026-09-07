"""Counters for static cohort population."""

from prometheus_client import Counter

COHORT_POPULATION_OUTCOMES = Counter(
    "cohort_population_outcomes_total",
    "Static cohort population attempts that reached an outcome, by source",
    ["source", "outcome"],
)

COHORT_POPULATION_WORK_UNITS = Counter(
    "cohort_population_work_units_total",
    "Population work units completed, by source and phase",
    ["source", "phase"],
)

COHORT_POPULATION_RECOVERIES = Counter(
    "cohort_population_recoveries_total",
    "Operations the dispatcher put back to work, by why they needed it",
    ["reason"],
)
