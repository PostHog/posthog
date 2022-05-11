export interface FrontendAppSceneProps {
    id: number
    url: string
    config: Record<string, any>
}

export interface FrontendAppSceneLogicProps {
    /** Used as the logic's key */
    id: number
}
