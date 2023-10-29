import clsx from 'clsx'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { useActions, useValues } from 'kea'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'

export const MenuHeader = (): JSX.Element => {
    const { searchTerm } = useValues(actionsLogic)
    const { setSearchTerm } = useActions(actionsLogic)

    return (
        <>
            <LemonInput
                autoFocus
                fullWidth
                placeholder="Search"
                type={'search'}
                value={searchTerm}
                className={clsx('mb-1 rounded-b-0')}
                onChange={(s) => setSearchTerm(s)}
            />
        </>
    )
}
