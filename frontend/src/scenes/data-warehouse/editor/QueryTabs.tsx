import { QueryPane } from './QueryPane'
import { ResultPane } from './ResultPane'

export function QueryTabs(): JSX.Element {
    return (
        <div className="flex flex-1 flex-col h-full bg-bg-3000-dark">
            <QueryPane />
            <ResultPane />
        </div>
    )
}
