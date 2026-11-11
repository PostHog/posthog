from parameterized import parameterized

from products.ai_observability.backend.hog import compile_ai_observability_hog
from products.ai_observability.backend.logic.eval_suggestions import catalog
from products.ai_observability.backend.models.evaluation_configs import validate_evaluation_configs


@parameterized.expand(sorted(catalog.templates()))
def test_shared_template_is_a_valid_evaluation(key: str) -> None:
    template = catalog.template(key)
    validate_evaluation_configs(
        template.evaluation_type, template.output_type, template.evaluation_config(), template.output_config
    )
    if template.source is not None:
        assert compile_ai_observability_hog(template.source, "destination")
