package core

import "testing"

func TestFindLegacyObjectStorageVolume(t *testing.T) {
	tests := []struct {
		name    string
		volumes []string
		want    string
	}{
		{
			// The SeaweedFS replacement mounts objectstorage-data. Matching it would make
			// the installer warn forever and point a salvage run at the live volume.
			name:    "ignores the seaweedfs volume",
			volumes: []string{"posthog_objectstorage-data", "posthog_postgres-data"},
			want:    "",
		},
		{
			name:    "finds the compose-prefixed minio volume",
			volumes: []string{"posthog_objectstorage-data", "posthog_objectstorage"},
			want:    "posthog_objectstorage",
		},
		{
			name:    "finds an unprefixed minio volume",
			volumes: []string{"objectstorage"},
			want:    "objectstorage",
		},
		{
			name:    "tolerates the blank line docker volume ls leaves",
			volumes: []string{"posthog_objectstorage", ""},
			want:    "posthog_objectstorage",
		},
		{
			name:    "reports nothing on a new install",
			volumes: []string{},
			want:    "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := findLegacyObjectStorageVolume(tt.volumes); got != tt.want {
				t.Errorf("findLegacyObjectStorageVolume(%v) = %q, want %q", tt.volumes, got, tt.want)
			}
		})
	}
}
