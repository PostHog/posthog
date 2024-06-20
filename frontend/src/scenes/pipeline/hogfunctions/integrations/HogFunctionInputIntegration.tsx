import { HogFunctionIntegrationSlackConnection } from './HogFunctionInputIntegrationSlack'
import { HogFunctionInputIntegrationProps } from './types'

export function HogFunctionInputIntegration({ schema, ...props }: HogFunctionInputIntegrationProps): JSX.Element {
    if (schema.integration === 'slack') {
        return <HogFunctionIntegrationSlackConnection {...props} />
    }
    return (
        <div className="text-danger">
            <p>Unsupported integration type: {schema.integration}</p>
        </div>
    )
}
