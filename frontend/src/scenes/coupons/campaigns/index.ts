import { everyCampaign } from './every'
import { lennyCampaign } from './lenny'
import { lennySummitCampaign } from './lennySummit'
import { productAcademyCampaign } from './productAcademy'
import { CampaignConfig } from './types'

export const campaignConfigs: Record<string, CampaignConfig> = {
    every: everyCampaign,
    lenny: lennyCampaign,
    'lenny-summit': lennySummitCampaign,
    'product-academy': productAcademyCampaign,
}
