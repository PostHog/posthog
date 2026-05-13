import { BuiltLogic, Logic } from 'kea'
import { urlToAction } from 'kea-router'
import { UrlToActionPayload } from 'kea-router/lib/types'

export const tabAwareUrlToAction = <L extends Logic = Logic>(
    input: UrlToActionPayload<L> | ((logic: BuiltLogic<L>) => UrlToActionPayload<L>)
): ((logic: BuiltLogic<L>) => void) => {
    return urlToAction<L>(input)
}
