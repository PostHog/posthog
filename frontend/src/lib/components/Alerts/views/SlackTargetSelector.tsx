import { useValues } from 'kea'
import { useEffect } from 'react'
import { hogFunctionListLogic } from 'scenes/pipeline/hogfunctions/list/hogFunctionListLogic'
import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

type SlackTargetSelectorProps = {
    value: string | null
    onChange: (targetId: string | null) => void
}

export function SlackTargetSelector({ value, onChange }: SlackTargetSelectorProps): JSX.Element {
    const logicKey = 'alert-slack-target'
    const logic = hogFunctionListLogic({
        logicKey,
        type: 'internal_destination',
    })

    const { hogFunctions } = useValues(logic)

    // We need to listen to HogFunction selection in the list
    // Since we can't directly modify LinkedHogFunctions, we'll monitor the hogFunctions array
    // and call onChange when we detect a new HogFunction was added that matches our template
    useEffect(() => {
        // Find slack HogFunctions that match our template
        const slackHogFunctions = hogFunctions.filter((hf) =>
            hf.template?.sub_templates?.some((st) => st.id === 'insight-alert-firing')
        )

        // If we have a slack HogFunction and no current value, select it
        if (slackHogFunctions.length > 0 && !value) {
            onChange(slackHogFunctions[0].id)
        }
    }, [hogFunctions, value, onChange])

    // Load HogFunctions when component mounts
    useEffect(() => {
        logic.actions.loadHogFunctions()
    }, [])

    return (
        <LinkedHogFunctions
            logicKey={logicKey}
            type="internal_destination"
            subTemplateId="insight-alert-firing"
            filters={{}}
        />
    )
}
