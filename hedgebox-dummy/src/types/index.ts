export interface HedgeboxFile {
    id: string
    name: string
    type: string
    size: number
    uploadedAt: Date
    sharedLink?: string
}

export interface HedgeboxUser {
    id: string
    name: string
    email: string
    plan: 'personal/free' | 'personal/pro' | 'business/standard' | 'business/enterprise'
}

export interface HedgeboxAccount {
    id: string
    name: string
    plan: 'personal/free' | 'personal/pro' | 'business/standard' | 'business/enterprise'
    usedStorage: number
    maxStorage: number
    teamMembers: HedgeboxUser[]
    files: HedgeboxFile[]
}
