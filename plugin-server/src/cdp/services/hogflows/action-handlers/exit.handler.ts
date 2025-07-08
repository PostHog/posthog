import { ActionHandler, ActionHandlerResult } from './action-handler.interface'

export class ExitHandler implements ActionHandler {
    execute(): ActionHandlerResult {
        return { finished: true }
    }
}
