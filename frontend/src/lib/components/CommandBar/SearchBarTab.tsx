import { useActions, useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { RefObject } from 'react'

import { resultTypeToName } from './constants'
import { searchBarLogic } from './searchBarLogic'
import { ResultTypeWithAll } from './types'

type SearchBarTabProps = {
    type: ResultTypeWithAll
    active: boolean
    count?: number | null
    inputRef: RefObject<HTMLInputElement>
}

export const SearchBarTab = ({ type, active, count, inputRef }: SearchBarTabProps): JSX.Element => {
    const { setActiveTab } = useActions(searchBarLogic)
    return (
        <div
            className={`SearchBarTab flex items-center px-4 py-2 cursor-pointer text-xs whitespace-nowrap border-t-2 ${
                active ? 'SearchBarTab__active font-bold border-primary-3000' : 'border-transparent'
            }`}
            onClick={() => {
                setActiveTab(type)
                inputRef.current?.focus()
            }}
        >
            {resultTypeToName[type]}
            <Count type={type} active={active} count={count} />
        </div>
    )
}

type CountProps = {
    type: ResultTypeWithAll
    active: boolean
    count?: number | null
}

const Count = ({ type, active, count }: CountProps): JSX.Element | null => {
    const { searchResponseLoading } = useValues(searchBarLogic)

    if (type === 'all') {
        return null
    } else if (active && searchResponseLoading) {
        return <Spinner className="ml-0.5" />
    } else if (count != null) {
        return <span className="ml-1 text-xxs text-muted-3000">{count}</span>
    } else {
        return <span className="ml-1 text-xxs text-muted-3000">&mdash;</span>
    }
}
