# Anomaly detectors

User insight alerts and signals anomaly scoring share these detectors.

- Detector config describes how a detector scores: threshold, window, preprocessing, and model parameters.
- Do not add a detector option for the rule of one consumer, such as flag suppression, direction, cooldowns, or deduplication. Put that rule in the consumer. For signals, that is [`products/signals/backend/anomaly_scores/scoring.py`](../../../../products/signals/backend/anomaly_scores/scoring.py).
- Do not change the score of a detector to get the flag behavior that one consumer wants. A consumer can change the flag that it derives from the score.
- A new detector option needs a reason that applies to all consumers.
