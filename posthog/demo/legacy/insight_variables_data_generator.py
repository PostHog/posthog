from posthog.models import Dashboard, DashboardTile, Insight, InsightVariable, Person

from .data_generator import DataGenerator


class InsightVariablesDataGenerator(DataGenerator):
    def create_missing_events_and_properties(self):
        pass

    def populate_person_events(self, person: Person, distinct_id: str, index: int):
        pass

    def create_actions_dashboards(self):
        var1 = InsightVariable.objects.create(
            team=self.team, name="Variable 1", code_name="variable_1", default_value=10, type="Number"
        )
        var2 = InsightVariable.objects.create(
            team=self.team, name="Variable 2", code_name="variable_2", default_value=10, type="Number"
        )
        var3 = InsightVariable.objects.create(
            team=self.team, name="Variable 3", code_name="variable_3", default_value=10, type="Number"
        )
        var4 = InsightVariable.objects.create(
            team=self.team, name="Variable 4", code_name="variable_4", default_value=10, type="Number"
        )

        dashboard = Dashboard.objects.create(
            name="Insight variables",
            team=self.team,
            variables={
                str(var2.id): {
                    "code_name": var2.code_name,
                    "variableId": str(var2.id),
                    "value": 20,  # override
                }
            },
        )

        # We test five different configurations of insight variables on dashboards:
        # 1. The default value of the variable.
        # 2. The dashboard overriding the variable value.
        # 3. The insight overriding the variable value.
        # 4. A temporary variable override, through the URL.
        # 5. A missing variable, which should raise a validation error.
        insight1 = Insight.objects.create(
            team=self.team,
            name="Variable default",
            description="Shows the default value of the variable.",
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT {variables.variable_1}",
                    "variables": {
                        str(var1.id): {
                            "code_name": var1.code_name,
                            "variableId": str(var1.id),
                        }
                    },
                },
                "display": "BoldNumber",
            },
        )
        insight2 = Insight.objects.create(
            team=self.team,
            name="Dashboard override",
            description="Shows a dashboard override of the variable.",
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT {variables.variable_2}",
                    "variables": {
                        str(var2.id): {
                            "code_name": var2.code_name,
                            "variableId": str(var2.id),
                        }
                    },
                },
                "display": "BoldNumber",
            },
        )
        insight3 = Insight.objects.create(
            team=self.team,
            name="Insight override",
            description="Shows an insight override of the variable.",
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT {variables.variable_3}",
                    "variables": {
                        str(var3.id): {
                            "code_name": var3.code_name,
                            "variableId": str(var3.id),
                            "value": 30,  # override
                        }
                    },
                },
                "display": "BoldNumber",
            },
        )
        insight4 = Insight.objects.create(
            team=self.team,
            name="Temporary override",
            description="Shows a temporary variable override through the URL.",
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT {variables.variable_4}",
                    "variables": {
                        str(var4.id): {
                            "code_name": var4.code_name,
                            "variableId": str(var4.id),
                        }
                    },
                },
                "display": "BoldNumber",
            },
        )
        insight5 = Insight.objects.create(
            team=self.team,
            name="Missing variable",
            description="Shows a validation error for a missing variable.",
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT {variables.var_missing}",
                    "variables": {
                        "missing_variable_id": {
                            "code_name": "var_missing",
                            "variableId": "missing_variable_id",
                        }
                    },
                },
                "display": "BoldNumber",
            },
        )

        DashboardTile.objects.create(insight=insight1, dashboard=dashboard)
        DashboardTile.objects.create(insight=insight2, dashboard=dashboard)
        DashboardTile.objects.create(insight=insight3, dashboard=dashboard)
        DashboardTile.objects.create(insight=insight4, dashboard=dashboard)
        DashboardTile.objects.create(insight=insight5, dashboard=dashboard)
        dashboard.save()
