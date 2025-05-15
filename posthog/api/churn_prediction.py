from rest_framework import (
    exceptions,
    request,
)
from posthog.api.utils import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

# Data manipulation
import pandas as pd
import numpy as np

# Machine learning
from catboost import CatBoostClassifier, Pool
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    confusion_matrix,
    classification_report,
)
from sklearn.preprocessing import StandardScaler

from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner
from posthog.api.routing import TeamAndOrgViewSetMixin

# Set random seed for reproducibility
np.random.seed(42)


class ChurnPredictionViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "INTERNAL"

    @action(methods=["POST"], detail=False)
    def train_model(self, request: request.Request, **kwargs):
        if "dataset_query" not in request.data:
            raise exceptions.ValidationError("Missing dataset query")

        np.random.seed(42)

        query_runner = get_query_runner(
            query={
                "kind": "HogQLQuery",
                "query": request.data["dataset_query"],
            },
            team=self.team,
        )

        query_result = query_runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        results = query_result.results

        # Convert results to DataFrame
        df = pd.DataFrame(results)

        # Split features and target
        X = df.iloc[:, :-1]  # All columns except last
        y = df.iloc[:, -1]  # Last column is target

        # Identify categorical features
        cat_features = X.select_dtypes(include=["object"]).columns.tolist()

        # Split data with stratification
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

        # Create CatBoost pools
        train_pool = Pool(X_train, y_train, cat_features=cat_features)
        test_pool = Pool(X_test, y_test, cat_features=cat_features)

        # Define optimized parameters
        params = {
            "iterations": 1000,
            "learning_rate": 0.05,
            "depth": 6,
            "loss_function": "Logloss",
            "eval_metric": "AUC",
            "random_seed": 42,
            "early_stopping_rounds": 50,
            "verbose": False,
            "class_weights": [1, 20],  # Addressing class imbalance
            "l2_leaf_reg": 3,  # Regularization
            "random_strength": 1,  # Randomization strength
            "min_data_in_leaf": 5,  # Prevent overfitting
        }

        # Train model
        model = CatBoostClassifier(**params)
        model.fit(train_pool, eval_set=test_pool)

        # Get predictions and probabilities
        y_pred = model.predict(X_test)
        y_pred_proba = model.predict_proba(X_test)[:, 1]

        # Calculate metrics
        metrics = {
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "precision": float(precision_score(y_test, y_pred)),
            "recall": float(recall_score(y_test, y_pred)),
            "f1": float(f1_score(y_test, y_pred)),
            "roc_auc": float(roc_auc_score(y_test, y_pred_proba)),
            "classification_report": {
                str(k): v for k, v in classification_report(y_test, y_pred, output_dict=True).items()
            },
        }

        # Get feature importances
        feature_importances = model.get_feature_importance(train_pool)
        feature_names = [str(col) for col in X.columns]  # Convert all column names to strings

        # Create DataFrame for feature importance
        feature_importance_df = pd.DataFrame({"Feature": feature_names, "Importance": feature_importances})

        # Sort by importance
        feature_importance_df = feature_importance_df.sort_values("Importance", ascending=False).reset_index(drop=True)

        # Convert to dict for API response, excluding the target variable (last column)
        feature_importance = dict(zip(feature_importance_df["Feature"][:-1], feature_importance_df["Importance"][:-1]))

        # Get class distribution
        class_distribution = {str(k): float(v) for k, v in y.value_counts(normalize=True).round(4).items()}

        return Response(
            {
                "status": "success",
                "metrics": metrics,
                "feature_importance": feature_importance,
                "top_features": feature_importance_df[:-1].to_dict("records"),  # Exclude target variable
                "class_distribution": class_distribution,
                "categorical_features": [str(f) for f in cat_features],
                "total_features": len(X.columns),
            }
        )
