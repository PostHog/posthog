import { ExperimentTemplate } from './constants'

type ExperimentTemplateCardProps = {
    template: ExperimentTemplate
}

export const ExperimentTemplateCard = ({ template }: ExperimentTemplateCardProps): JSX.Element => {
    return (
        <div>
            <h3>{template.name}</h3>
            <p>{template.description}</p>
            <p>{template.experimentGoal}</p>
            <div>{template.icon}</div>
        </div>
    )
}
