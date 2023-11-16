import { useActions } from 'kea'

import { resultTypeToName } from './constants'
import { searchBarLogic } from './searchBarLogic'
import { ResultTypeWithAll } from './types'

type SearchBarTabProps = {
    type: ResultTypeWithAll
    active: boolean
    count?: number | null
}

export const SearchBarTab = ({ type, active, count }: SearchBarTabProps): JSX.Element => {
    const { setActiveTab } = useActions(searchBarLogic)
    return (
        <div
            className={`px-3 py-2 cursor-pointer text-xs whitespace-nowrap ${active && 'font-bold'}`}
            onClick={() => setActiveTab(type)}
        >
            {resultTypeToName[type]}
            {count != null && <span className="ml-1 text-xxs text-muted-3000">{count}</span>}
        </div>
    )
}
