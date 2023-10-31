import { useActions } from 'kea'

import { resultTypeToName } from './constants'
import { searchBarLogic } from './searchBarLogic'
import { ResultTypeWithAll } from './types'

type SearchBarTabProps = {
    type: ResultTypeWithAll
    isFirst: boolean
    active: boolean
    count?: number | null
}

const SearchBarTab = ({ type, isFirst = false, active, count }: SearchBarTabProps): JSX.Element => {
    const { setActiveTab } = useActions(searchBarLogic)
    return (
        <div
            className={`${isFirst ? 'px-5' : 'px-3'} py-2 cursor-pointer text-xs ${active && 'font-bold'}`}
            onClick={() => setActiveTab(type)}
        >
            {resultTypeToName[type]}
            {count != null && <span className="ml-1 text-xxs text-muted-3000">{count}</span>}
        </div>
    )
}

export default SearchBarTab
