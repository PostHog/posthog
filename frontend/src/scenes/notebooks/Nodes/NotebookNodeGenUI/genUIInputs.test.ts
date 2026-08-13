import { validateGenUIInputs } from './genUIInputs'

describe('validateGenUIInputs', () => {
    it.each([
        [' trims and separates names ', ['trims', 'and', 'separates', 'names'], null],
        ['events_df, users_df', ['events_df', 'users_df'], null],
        ['events_df, events_df', [], 'Dataframe "events_df" is listed more than once.'],
        ['invalid-name', [], '"invalid-name" is not a valid dataframe name.'],
        ['a,b,c,d,e', [], 'Choose no more than 4 dataframes.'],
    ])('validates %s', (inputs, names, error) => {
        expect(validateGenUIInputs(inputs)).toEqual({ names, error })
    })
})
