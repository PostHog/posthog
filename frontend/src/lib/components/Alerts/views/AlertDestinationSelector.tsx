// import { useValues } from 'kea'
// import { useEffect } from 'react'
// import { hogFunctionListLogic } from 'scenes/pipeline/hogfunctions/list/hogFunctionListLogic'
import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

export function AlertDestinationSelector(): JSX.Element {
    // const logic = hogFunctionListLogic({
    //     logicKey: ALERT_DESTINATION_LOGIC_KEY,
    //     type: 'internal_destination',
    // })

    // const { hogFunctions } = useValues(logic)

    // useEffect(() => {
    //     const alertHogFunctions = hogFunctions.filter((hf) =>
    //         hf.template?.sub_templates?.some((st) => st.id === 'insight-alert-firing')
    //     )

    //     if (alertHogFunctions.length > 0 && !value) {
    //         onChange(alertHogFunctions[0].id)
    //     }
    // }, [hogFunctions, value, onChange])

    // useEffect(() => {
    //     logic.actions.loadHogFunctions()
    // }, [])

    return (
        <LinkedHogFunctions
            logicKey="insight-alert-firing"
            type="internal_destination"
            subTemplateId="insight-alert-firing"
            filters={{}}
        />
    )
}
