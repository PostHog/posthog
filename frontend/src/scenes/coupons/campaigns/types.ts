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
    HeroImage?: React.FC<any>
}
