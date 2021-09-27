import { ExpectFunction } from '~/test/kea-test-utils'
import { BuiltLogic, getContext, LogicWrapper } from 'kea'

export const toMount: ExpectFunction<BuiltLogic | LogicWrapper | (BuiltLogic | LogicWrapper)[]> = {
    common(logic, otherLogics) {
        const {
            mount: { mounted },
        } = getContext()
        const logics = [logic, ...(Array.isArray(otherLogics) ? otherLogics : [otherLogics])]

        for (const logicToMount of logics) {
            const pathString = '_isKeaBuild' in logicToMount ? logicToMount.pathString : logicToMount.build().pathString
            if (!mounted[pathString]) {
                throw new Error(`Logic "${pathString}" is not mounted, even though we expect it to be.`)
            }
        }
    },
}
