import { folderNameToModelSegment } from './modelNamespaceTree'

describe('folderNameToModelSegment', () => {
    test.each([
        ['Scratch', 'scratch'],
        ['Q3 reports', 'q3_reports'],
        ['already_snake', 'already_snake'],
        ['  --Sales & Ops--  ', 'sales_ops'],
        ['a__b..c', 'a_b_c'],
        ['2024 plans', '_2024_plans'],
        ['Ünïcode', 'n_code'],
        ['!!!', ''],
    ])('%s becomes %s', (folderName, segment) => {
        expect(folderNameToModelSegment(folderName)).toEqual(segment)
    })
})
