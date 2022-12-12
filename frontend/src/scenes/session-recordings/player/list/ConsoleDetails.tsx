import ReactJson from 'react-json-view'

export interface ConsoleDetailsProps {
    json: Record<string, any> | any[]
}

export function ConsoleDetails({ json }: ConsoleDetailsProps): JSX.Element {
    return <ReactJson src={json} />
}
