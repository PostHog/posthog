import { everyCampaign } from './every'
import { lennyCampaign } from './lenny'
import { productAcademyCampaign } from './productAcademy'
import { CampaignConfig } from './types'

export const campaignConfigs: Record<string, CampaignConfig> = {
    every: everyCampaign,
    lenny: lennyCampaign,
    'product-academy': productAcademyCampaign,
}
