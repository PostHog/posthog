import { actions, kea, key, path, props, reducers } from 'kea'

import type { navPanelAdvertisementLogicType } from './NavPanelAdvertisementLogicType'

export type NavPanelAdvertisementLogicProps = {
    productKey: string
}

export const navPanelAdvertisementLogic = kea<navPanelAdvertisementLogicType>([
    path(['lib', 'components', 'NavPanelAdvertisementLogic']),
    props({} as NavPanelAdvertisementLogicProps),
    key(({ productKey }) => productKey),
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
