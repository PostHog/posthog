import { ResultTypesWithAll } from './types'

const resultTypeToName: Record<ResultTypesWithAll, string> = {
    all: 'All',
    dashboard: 'Dashboard',
    experiment: 'Experiment',
    feature_flag: 'Feature Flag',
}

type SearchBarTabProps = {
    type: ResultTypesWithAll
    isFirst: boolean
    active: boolean
    count?: number | null
}

const SearchBarTab = ({ type, isFirst = false, active, count }: SearchBarTabProps): JSX.Element => (
    <div className={`${isFirst ? 'px-5' : 'px-3'} py-2 cursor-pointer text-xs ${active && 'font-bold'}`}>
        {resultTypeToName[type]}
        {count && <span>{count}</span>}
    </div>
)

export default SearchBarTab
