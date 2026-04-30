import { everyCampaign } from './every'
import { lennyCampaign } from './lenny'
import { CampaignConfig } from './types'

export const campaignConfigs: Record<string, CampaignConfig> = {
    every: everyCampaign,
    lenny: lennyCampaign,
}
