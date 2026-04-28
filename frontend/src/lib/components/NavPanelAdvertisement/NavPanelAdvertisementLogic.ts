import { actions, kea, key, path, props, reducers } from 'kea'

import type { navPanelAdvertisementLogicType } from './NavPanelAdvertisementLogicType'

export type NavPanelAdvertisementLogicProps = {
    campaign: string
}

export const navPanelAdvertisementLogic = kea<navPanelAdvertisementLogicType>([
    path(['lib', 'components', 'NavPanelAdvertisementLogic']),
    props({} as NavPanelAdvertisementLogicProps),
    key(({ campaign }) => campaign),
    actions(() => ({
        hideAdvertisement: () => true,
        showAdvertisement: () => false,
    })),
    reducers(() => ({
        hidden: [
            false as boolean,
            { persist: true },
            {
                hideAdvertisement: () => true,
                showAdvertisement: () => false,
            },
        ],
    })),
])
