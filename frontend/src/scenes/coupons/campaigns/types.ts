export interface CampaignBenefit {
    title: string
    description: string | JSX.Element
}

export interface CampaignConfig {
    name: string
    heroTitle: string
    heroSubtitle: string
    benefits: CampaignBenefit[]
    eligibilityCriteria: string[]
    footerNote?: string | JSX.Element
    /** Keep the code form visible after a claim, for campaigns where an organization can redeem more than one code. */
    allowsRepeatClaims?: boolean
    HeroImage?: React.FC<any>
}
