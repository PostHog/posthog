import { BuiltLogic, Logic } from 'kea'

export const tabAwareScene = <L extends Logic = Logic>(): ((logic: BuiltLogic<L>) => void) => {
    return (logic: BuiltLogic<L>): void => {
        void logic
    }
}
