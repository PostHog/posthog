import {
    EVALUATION_TEMPLATE_CATEGORIES,
    EVALUATION_TEMPLATE_ICONS,
    type EvaluationTemplate,
    defaultEvaluationTemplates,
} from './templates'

describe('defaultEvaluationTemplates', () => {
    it.each(defaultEvaluationTemplates.map((template): [string, EvaluationTemplate] => [template.key, template]))(
        '%s uses a known icon and category',
        (_key, template) => {
            expect(EVALUATION_TEMPLATE_ICONS).toContain(template.icon)
            expect(EVALUATION_TEMPLATE_CATEGORIES).toContain(template.category)
        }
    )
})
