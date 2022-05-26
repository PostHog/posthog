import { appEditorUrl } from 'scenes/toolbar-launch/authorizedUrlsLogic'

describe('the authorized urls logic', () => {
    it('encodes an app url correctly', () => {
        expect(appEditorUrl('http://127.0.0.1:8000')).toEqual(
            '/api/user/redirect_to_site/?userIntent=add-action&appUrl=http%3A%2F%2F127.0.0.1%3A8000'
        )
    })
})
