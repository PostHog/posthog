import { resultTypeToName } from './constants'
import { ResultTypesWithAll } from './types'

type SearchBarTabProps = {
    type: ResultTypesWithAll
    isFirst: boolean
    active: boolean
    count?: number | null
}

const SearchBarTab = ({ type, isFirst = false, active, count }: SearchBarTabProps): JSX.Element => (
    <div className={`${isFirst ? 'px-5' : 'px-3'} py-2 cursor-pointer text-xs ${active && 'font-bold'}`}>
        {resultTypeToName[type]}
        {count != null && <span className="ml-1 text-xxs text-muted-3000">{count}</span>}
    </div>
)

export default SearchBarTab
