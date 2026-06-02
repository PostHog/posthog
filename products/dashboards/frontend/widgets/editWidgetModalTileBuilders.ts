export const widgetEditModalTileActions = {
    setTileName: (tileName: string) => ({ tileName }),
    setTileDescription: (tileDescription: string) => ({ tileDescription }),
}

export const widgetEditModalTileReducers = {
    tileName: [
        '',
        {
            setTileName: (_: string, { tileName }: { tileName: string }) => tileName,
        },
    ],
    tileDescription: [
        '',
        {
            setTileDescription: (_: string, { tileDescription }: { tileDescription: string }) => tileDescription,
        },
    ],
}

export const widgetEditModalSavingReducers = {
    saving: [
        false,
        {
            submit: () => true,
            submitSuccess: () => false,
            submitFailure: () => false,
        },
    ],
}
