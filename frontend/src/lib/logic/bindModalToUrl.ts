import { BuiltLogic, Logic } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

export interface BindModalToUrlOptions<L extends Logic = Logic> {
    urlKey: string
    openActionKey: keyof L['actionCreators'] & string
    closeActionKey: keyof L['actionCreators'] & string
    /** Name of the selector/reducer that's truthy when the modal is open. Used as loop guard. */
    isOpenKey: keyof L['values'] & string
}

/** Sync between a modal's open state and `?modal=<urlKey>`. Uses `replace`, preserves other params. */
export function bindModalToUrl<L extends Logic = Logic>({
    urlKey,
    openActionKey,
    closeActionKey,
    isOpenKey,
}: BindModalToUrlOptions<L>) {
    const buildUrl = (open: boolean): [string, Record<string, any>, Record<string, any>, { replace: true }] => {
        const { pathname, searchParams, hashParams } = router.values.currentLocation
        const next = { ...searchParams }
        if (open) {
            next.modal = urlKey
        } else if (next.modal === urlKey) {
            delete next.modal
        }
        return [pathname, next, hashParams, { replace: true }]
    }

    return (logic: BuiltLogic<L>): void => {
        actionToUrl(() => ({
            [openActionKey]: () => buildUrl(true),
            [closeActionKey]: () => buildUrl(false),
        }))(logic)

        urlToAction(({ actions, values }) => ({
            '*': (_params, searchParams) => {
                const shouldBeOpen = searchParams.modal === urlKey
                if (shouldBeOpen !== !!values[isOpenKey]) {
                    ;(actions as any)[shouldBeOpen ? openActionKey : closeActionKey]()
                }
            },
        }))(logic)
    }
}
