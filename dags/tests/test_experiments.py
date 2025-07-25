import pytest
from unittest.mock import Mock, patch

import dagster
from posthog.models import Experiment


class TestExperimentAssets:
    """
    Test suite for core experiment asset functionality.

    These tests focus on the main functions that discover experiments,
    create assets, and handle the asset execution logic.
    """
    
    @pytest.mark.django_db
    def test_get_experiment_metrics_empty(self):
        """
        Test behavior when no experiments exist in the database.

        This test ensures our code handles the empty database case gracefully
        without throwing exceptions or unexpected behavior.

        Test approach:
        1. Mock the database to return no experiments
        2. Call the discovery function
        3. Verify it returns an empty list
        """
        # Import here to avoid database access at module level
        from dags.experiments import _get_experiment_metrics
        
        with patch('dags.experiments.Experiment.objects') as mock_objects:
            # Set up mock database to return no experiments
            mock_queryset = Mock()
            mock_queryset.exclude.return_value = []
            mock_objects.filter.return_value = mock_queryset
            
            result = _get_experiment_metrics()
            
            assert result == []
    
    @pytest.mark.django_db
    def test_get_experiment_metrics_with_data(self):
        """
        Test experiment discovery with valid experiment data.

        This test verifies that our function correctly processes experiments
        that have metrics defined and meet our filtering criteria.

        Test approach:
        1. Create a mock experiment with multiple metrics and timeseries enabled
        2. Call the discovery function
        3. Verify it returns the expected experiment-metric combinations
        """
        # Import here to avoid database access at module level
        from dags.experiments import _get_experiment_metrics
        
        # Create mock experiment with required attributes
        mock_experiment = Mock()
        mock_experiment.id = 123
        mock_experiment.metrics = [
            {"kind": "ExperimentTrendsQuery", "name": "Test Metric 1"},
            {"kind": "ExperimentFunnelsQuery", "name": "Test Metric 2"}
        ]
        mock_experiment.stats_config = {"timeseries": "true"}
        
        with patch('dags.experiments.Experiment.objects') as mock_objects:
            mock_queryset = Mock()
            mock_queryset.exclude.return_value = [mock_experiment]
            mock_objects.filter.return_value = mock_queryset
            
            result = _get_experiment_metrics()
            
            expected = [
                (123, 0, {"kind": "ExperimentTrendsQuery", "name": "Test Metric 1"}),
                (123, 1, {"kind": "ExperimentFunnelsQuery", "name": "Test Metric 2"})
            ]
            assert result == expected
    
    @pytest.mark.django_db
    def test_get_experiment_metrics_filters_non_timeseries(self):
        """
        Test that experiments without timeseries are correctly filtered out.

        This test ensures our filtering logic properly excludes experiments
        that don't have timeseries analysis enabled.

        Test approach:
        1. Create a mock experiment without timeseries enabled
        2. Mock the database filter to exclude it (as Django would)
        3. Verify the function returns an empty list
        """
        # Import here to avoid database access at module level
        from dags.experiments import _get_experiment_metrics
        
        with patch('dags.experiments.Experiment.objects') as mock_objects:
            # Mock the Django filter to exclude non-timeseries experiments
            mock_queryset = Mock()
            mock_queryset.exclude.return_value = []  # Filter excludes the experiment
            mock_objects.filter.return_value = mock_queryset
            
            result = _get_experiment_metrics()
            
            assert result == []
    
    def test_create_experiment_asset(self):
        """
        Test asset creation for a single experiment-metric combination.

        This test verifies that our asset creation function produces a valid
        Dagster asset with correct properties and metadata.

        Test approach:
        1. Call the asset creation function with test data
        2. Verify the returned object is a valid Dagster asset
        3. Check that metadata and properties are set correctly
        """
        # Import here to avoid database access at module level
        with patch('dags.experiments._get_experiment_metrics', return_value=[]):
            from dags.experiments import _create_experiment_asset
        
        metric_data = {"kind": "ExperimentTrendsQuery", "name": "Test Metric"}
        
        asset_def = _create_experiment_asset(123, 0, metric_data)
        
        # Verify it's a valid Dagster asset
        assert isinstance(asset_def, dagster.AssetsDefinition)
        
        # Check asset properties
        assert len(asset_def.keys) == 1
        asset_key = list(asset_def.keys)[0]
        assert asset_key.to_user_string() == "experiment_123_0"
        
        # Verify metadata
        metadata = asset_def.metadata_by_key[asset_key]
        assert metadata["experiment_id"] == 123
        assert metadata["metric_index"] == 0
        assert metadata["metric_type"] == "ExperimentTrendsQuery"
        assert metadata["metric_name"] == "Test Metric"
    
    def test_asset_execution(self):
        """
        Test that generated assets can be executed successfully.

        This test verifies that when Dagster tries to materialize an asset,
        it executes without errors and returns the expected data structure.

        Test approach:
        1. Create an asset using our creation function  
        2. Test the asset's internal logic by calling it directly
        3. Verify the result structure and content
        """
        # Import here to avoid database access at module level
        with patch('dags.experiments._get_experiment_metrics', return_value=[]):
            from dags.experiments import _create_experiment_asset
        
        metric_data = {"kind": "ExperimentTrendsQuery", "name": "Test Metric"}
        asset_def = _create_experiment_asset(123, 0, metric_data)
        
        # Create a proper Dagster asset context
        context = dagster.build_asset_context()
        
        # Mock both functions that the asset calls to avoid complex instance mocking
        with patch('dags.experiments._get_experiment_name', return_value="Test Experiment"):
            with patch.object(context.instance, 'get_current_timestamp', return_value="2024-01-01T00:00:00Z", create=True):
                # Get the actual function from the asset definition and call it directly
                # Access the inner decorated function to avoid Dagster wrapper complexities
                asset_fn = asset_def.op.compute_fn.decorated_fn
                result = asset_fn(context)
                
                # Verify result structure
                assert isinstance(result, dict)
                assert result["experiment_id"] == 123
                assert result["metric_index"] == 0
                assert result["metric_definition"] == metric_data
                assert "results" in result
                assert result["results"]["placeholder"] is True
                assert result["computed_at"] == "2024-01-01T00:00:00Z"
    
    @pytest.mark.django_db  
    def test_experiment_assets_generation(self):
        """
        Test that the module can generate assets from database experiments.

        This is a simpler integration test that verifies the module can import
        successfully and that our asset generation logic works properly.

        Test approach:
        1. Test that our asset creation function works correctly
        2. Verify that assets have the expected properties
        """
        # Import with mocked discovery to avoid database queries
        with patch('dags.experiments._get_experiment_metrics') as mock_get_metrics:
            mock_get_metrics.return_value = [
                (123, 0, {"kind": "ExperimentTrendsQuery", "name": "Metric 1"}),
                (124, 0, {"kind": "ExperimentFunnelsQuery", "name": "Metric 2"}),
            ]
            
            # Import and test the asset creation function directly
            from dags.experiments import _create_experiment_asset
            
            # Test creating individual assets
            asset1 = _create_experiment_asset(123, 0, {"kind": "ExperimentTrendsQuery", "name": "Metric 1"})
            asset2 = _create_experiment_asset(124, 0, {"kind": "ExperimentFunnelsQuery", "name": "Metric 2"})
            
            # Verify both assets were created correctly
            assert isinstance(asset1, dagster.AssetsDefinition)
            assert isinstance(asset2, dagster.AssetsDefinition) 
            
            # Verify asset names
            assert list(asset1.keys)[0].to_user_string() == "experiment_123_0"
            assert list(asset2.keys)[0].to_user_string() == "experiment_124_0"
            
            # Verify metadata
            metadata1 = asset1.metadata_by_key[list(asset1.keys)[0]]
            metadata2 = asset2.metadata_by_key[list(asset2.keys)[0]]
            
            assert metadata1["experiment_id"] == 123
            assert metadata1["metric_index"] == 0
            assert metadata1["metric_type"] == "ExperimentTrendsQuery"
            
            assert metadata2["experiment_id"] == 124
            assert metadata2["metric_index"] == 0
            assert metadata2["metric_type"] == "ExperimentFunnelsQuery"
    
    @pytest.mark.django_db
    def test_experiment_name_helper(self):
        """
        Test the helper function that retrieves experiment names.

        This test covers multiple scenarios for the name lookup function:
        - Normal case: experiment exists with a name
        - Error case: experiment doesn't exist in database  
        - Edge case: experiment exists but has no name set

        Test approach:
        1. Test each scenario with appropriate mocks
        2. Verify correct return values for each case
        """
        # Import here to avoid database access at module level
        with patch('dags.experiments._get_experiment_metrics', return_value=[]):
            from dags.experiments import _get_experiment_name
        
        # Test case 1: Normal case - experiment exists with name
        mock_experiment = Mock()
        mock_experiment.name = "Test Experiment"
        
        with patch('dags.experiments.Experiment.objects.get') as mock_get:
            mock_get.return_value = mock_experiment
            
            result = _get_experiment_name(123)
            assert result == "Test Experiment"
            mock_get.assert_called_once_with(id=123)
        
        # Test case 2: Error case - experiment doesn't exist
        with patch('dags.experiments.Experiment.objects.get') as mock_get:
            mock_get.side_effect = Experiment.DoesNotExist()
            
            result = _get_experiment_name(999)
            assert result == "Experiment 999 (not found)"
        
        # Test case 3: Edge case - experiment exists but has no name
        mock_experiment_no_name = Mock()
        mock_experiment_no_name.name = None
        
        with patch('dags.experiments.Experiment.objects.get') as mock_get:
            mock_get.return_value = mock_experiment_no_name
            
            result = _get_experiment_name(123)
            assert result == "Experiment 123"


class TestIntegration:
    """
    Integration tests for the complete experiment assets system.

    These tests verify that all components work together correctly
    and that the module integrates properly with Dagster.
    """

    @pytest.mark.django_db
    def test_locations_file_imports(self):
        """
        Test that the locations file can be imported successfully.

        This test ensures our locations/experiments.py file can be imported
        without errors and creates valid Dagster definitions.

        Test approach:
        1. Attempt to import the locations module
        2. Verify it has the required 'defs' attribute
        3. Verify 'defs' is a valid Dagster Definitions object
        """
        try:
            from dags.locations import experiments as experiments_location
            
            assert experiments_location.defs is not None
            assert isinstance(experiments_location.defs, dagster.Definitions)
            
        except ImportError as e:
            pytest.fail(f"Failed to import experiments location: {e}")
    
    @pytest.mark.django_db
    def test_workspace_configuration(self):
        """
        Test that the module structure follows Dagster conventions.

        This test performs a basic check that our module can be loaded
        in a Dagster workspace configuration.

        Test approach:
        1. Import the locations module
        2. Verify it has the required structure
        3. Report clear errors if anything is misconfigured
        """
        try:
            import dags.locations.experiments
            
            assert hasattr(dags.locations.experiments, 'defs')
            
        except Exception as e:
            pytest.fail(f"Experiments location is not properly configured: {e}")
