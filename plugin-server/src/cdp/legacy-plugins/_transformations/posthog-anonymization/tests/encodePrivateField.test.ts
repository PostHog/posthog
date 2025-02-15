import { encodePrivateField } from '../src/encodePrivateField'

describe('encodePrivateField', () => {
    it('returns encoded field when input is not empty string', () => {
        const actual = encodePrivateField('user_id', '1234567890')

        expect(actual).toMatchInlineSnapshot(`"ae2897db84a09e2729c95f8d41a16b4abdfcbf5e9a59c792877b7ba86c17bd03"`)
    })
})
