import { surveySentHandler } from './handlers/surveys/surveySent'
import { surveyShownHandler } from './handlers/surveys/surveyShown'
import { internalEventHandlerRegistry } from './registry'

export { internalEventHandlerRegistry } from './registry'

// register internal event handlers
internalEventHandlerRegistry.register(surveyShownHandler)
internalEventHandlerRegistry.register(surveySentHandler)
