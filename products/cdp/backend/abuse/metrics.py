from prometheus_client import Counter, Histogram

CLASSIFICATIONS = Counter(
    "cdp_abuse_classifications_total",
    "Shadow abuse classifications of saved hog functions",
    labelnames=["function_type", "verdict", "outcome"],
)
RISK_SCORE = Histogram(
    "cdp_abuse_classification_risk_score",
    "Highest probability among the abuse questions",
    labelnames=["function_type"],
    buckets=(0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0),
)
LATENCY = Histogram(
    "cdp_abuse_classification_latency_seconds",
    "Time for Jev to answer one classification",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)
INPUT_TOKENS = Counter(
    "cdp_abuse_classification_input_tokens_total",
    "Jev input tokens spent on shadow abuse classifications",
    labelnames=["function_type"],
)
ERRORS = Counter(
    "cdp_abuse_classification_errors_total",
    "Shadow abuse classifications that ended without a verdict",
    labelnames=["reason"],
)
RULE_HITS = Counter(
    "cdp_abuse_rule_hits_total",
    "Exact abuse rules that matched a reported hog function",
    labelnames=["rule"],
)
