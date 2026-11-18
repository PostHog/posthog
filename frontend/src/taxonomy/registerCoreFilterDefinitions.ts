// For entry points that render filters on first paint without sceneLogic (the exporter, render-query, the toolbar,
// tests, Storybook). Never import this from the app, because it puts the taxonomy back on the eager path.
import coreFilterDefinitionsByGroup from './core-filter-definitions-by-group.json'
import { setCoreFilterDefinitions } from './taxonomy'

setCoreFilterDefinitions(coreFilterDefinitionsByGroup)
