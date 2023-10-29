import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { useActions, useValues } from 'kea'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'

export const MenuHeader = (): JSX.Element => {
    const { wildcardHref } = useValues(currentPageLogic)
    const { setWildcardHref } = useActions(currentPageLogic)

    return (
        <div>
            <LemonInput value={wildcardHref} onChange={setWildcardHref} />
            <div className="text-muted pl-2 pt-1">Use * as a wildcard</div>
        </div>
    )
}
