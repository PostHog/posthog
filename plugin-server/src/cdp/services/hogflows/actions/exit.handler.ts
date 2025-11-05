import { ActionHandler, ActionHandlerResult } from './action.interface'

export class ExitHandler implements ActionHandler {
    execute(): ActionHandlerResult {
        return { finished: true }
    }
}
