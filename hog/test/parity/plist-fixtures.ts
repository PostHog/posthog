// iOS Info.plist files for `--info-plist`: XML, binary (made with `plutil -convert binary1`, with a
// non-ASCII version so it is stored as UTF-16), and one that names Xcode build settings.

export const INFO_PLIST_XML = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key>
	<string>en</string>
	<key>CFBundleIdentifier</key>
	<string>com.example.shop</string>
	<key>CFBundleShortVersionString</key>
	<string>3.4.0-r&#xE9;c</string>
	<key>CFBundleVersion</key>
	<string>57</string>
	<key>UIRequiredDeviceCapabilities</key>
	<array>
		<string>arm64</string>
	</array>
	<key>LSRequiresIPhoneOS</key>
	<true/>
</dict>
</plist>
`

export const INFO_PLIST_BINARY = Buffer.from(
    'YnBsaXN0MDDWAQIDBAUGBwgJCgsNXxAaQ0ZCdW5kbGVTaG9ydFZlcnNpb25TdHJpbmdfEBlDRkJ1bmRsZURldmVsb3BtZW50UmVnaW9uXxAPQ0ZCdW5kbGVWZXJzaW9uXxASQ0ZCdW5kbGVJZGVudGlmaWVyXxAcVUlSZXF1aXJlZERldmljZUNhcGFiaWxpdGllc18QEkxTUmVxdWlyZXNJUGhvbmVPU2oAMwAuADQALgAwAC0AYgDpAHQAYVJlblI1N18QEGNvbS5leGFtcGxlLnNob3ChDFVhcm02NAkIFTJOYHWUqb7BxNfZ3wAAAAAAAAEBAAAAAAAAAA4AAAAAAAAAAAAAAAAAAADg',
    'base64'
)

export const INFO_PLIST_SETTINGS = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key>
	<string>en</string>
	<key>CFBundleIdentifier</key>
	<string>$(PRODUCT_BUNDLE_IDENTIFIER:rfc1034identifier)</string>
	<key>CFBundleShortVersionString</key>
	<string>$(MARKETING_VERSION)</string>
	<key>CFBundleVersion</key>
	<string>\${CURRENT_PROJECT_VERSION}</string>
	<key>UIRequiredDeviceCapabilities</key>
	<array>
		<string>arm64</string>
	</array>
	<key>LSRequiresIPhoneOS</key>
	<true/>
</dict>
</plist>
`

export const XCODE_SETTINGS = {
    PRODUCT_BUNDLE_IDENTIFIER: 'com.example.settings',
    MARKETING_VERSION: '5.0.1',
    CURRENT_PROJECT_VERSION: '88',
}
