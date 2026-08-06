import userInteractionsSeed from '../../../../../../products/demo/backend/logic/dashboard_template_seeds/09_user_interactions.json'
import { USER_INTERACTIONS_TEMPLATE_NAME } from './SuggestedTemplateBanner'

describe('SuggestedTemplateBanner', () => {
    it('matches the seeded template name', () => {
        // The banner finds its template by name and renders nothing when there is no match, so a
        // rename on either side would take the suggestion away without any visible error.
        expect(userInteractionsSeed.template_name).toEqual(USER_INTERACTIONS_TEMPLATE_NAME)
    })
})
