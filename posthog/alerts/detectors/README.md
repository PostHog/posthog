# Alert Detectors Module

This module provides a modular anomaly detection system for PostHog alerts. Each detector type is implemented as a separate module for better maintainability and extensibility.

## Structure

```
detectors/
├── __init__.py          # Public API exports
├── base.py             # Base classes and common types
├── factory.py          # Factory function for creating detectors
├── threshold.py        # Threshold-based detection (legacy compatible)
├── zscore.py          # Z-Score statistical anomaly detection  
├── mad.py             # MAD (Median Absolute Deviation) detection
└── README.md          # This file
```

## Usage

```python
from posthog.alerts.detectors import create_detector, DetectorType, ValueType

# Create a Z-Score detector
detector = create_detector(DetectorType.ZSCORE, {
    "threshold": 2.0,
    "direction": "both",
    "min_samples": 10,
    "window_size": 50,
})

# Run detection on time series data
result = detector.detect(
    values=[1.0, 1.2, 0.8, 1.1, 5.0],  # Last value is anomaly
    series_name="Page Views",
    value_type=ValueType.RAW
)

print(f"Breach: {result.is_breach}")
print(f"Score: {result.detector_score}")
print(f"Messages: {result.breach_messages}")
```

## Detector Types

### ThresholdDetector
- **Type**: `DetectorType.THRESHOLD`
- **Purpose**: Traditional threshold-based alerts (maintains backward compatibility)
- **Config**: `bounds` (upper/lower), `threshold_type` (absolute/percentage)

### ZScoreDetector  
- **Type**: `DetectorType.ZSCORE`
- **Purpose**: Statistical anomaly detection using z-scores
- **Config**: `threshold` (default: 2.0), `direction`, `min_samples`, `window_size`

### MADDetector
- **Type**: `DetectorType.MAD` 
- **Purpose**: Robust statistical detection using Median Absolute Deviation
- **Config**: `threshold` (default: 3.0), `direction`, `min_samples`, `window_size`

## Adding New Detectors

1. Create a new `.py` file in this directory
2. Implement a class inheriting from `BaseDetector`
3. Add the detector type to `DetectorType` enum in `base.py`
4. Register it in the factory function in `factory.py`
5. Export it in `__init__.py`
6. Add comprehensive tests

Example:

```python
# new_detector.py
from .base import BaseDetector, DetectorType, DetectionResult, ValueType

class MyDetector(BaseDetector):
    @property
    def detector_type(self) -> DetectorType:
        return DetectorType.MY_DETECTOR
    
    def validate_config(self) -> None:
        # Validate configuration
        pass
    
    def detect(self, values, series_name="Series", value_type=ValueType.RAW):
        # Implement detection logic
        return DetectionResult(...)
```

## Testing

All detectors are comprehensively tested in `/posthog/alerts/test_detectors.py`. Run tests with:

```bash
python -m pytest posthog/alerts/test_detectors.py -v
```