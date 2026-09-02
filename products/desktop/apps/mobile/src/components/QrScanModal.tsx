import { CameraView, useCameraPermissions } from "expo-camera";
import { useCallback, useRef, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

export type QrScanResult = {
  apiKey: string;
  projectId: number;
};

type QrScanModalProps = {
  visible: boolean;
  onClose: () => void;
  onScan: (result: QrScanResult) => void;
};

function parseQrPayload(raw: string): QrScanResult | null {
  try {
    const parsed = JSON.parse(raw);
    const apiKey = typeof parsed.apiKey === "string" ? parsed.apiKey : null;
    const projectIdRaw = parsed.projectId;
    const projectId =
      typeof projectIdRaw === "number"
        ? projectIdRaw
        : typeof projectIdRaw === "string"
          ? Number(projectIdRaw)
          : NaN;
    if (!apiKey || !Number.isFinite(projectId) || projectId <= 0) {
      return null;
    }
    return { apiKey, projectId };
  } catch {
    return null;
  }
}

export function QrScanModal({ visible, onClose, onScan }: QrScanModalProps) {
  const [permission, requestPermission] = useCameraPermissions();
  const [error, setError] = useState<string | null>(null);
  const hasScannedRef = useRef(false);

  const handleBarcode = useCallback(
    (event: { data: string }) => {
      if (hasScannedRef.current) {
        return;
      }
      const parsed = parseQrPayload(event.data);
      if (!parsed) {
        setError("QR code is not a valid PostHog sign-in code");
        return;
      }
      hasScannedRef.current = true;
      onScan(parsed);
    },
    [onScan],
  );

  const handleClose = useCallback(() => {
    hasScannedRef.current = false;
    setError(null);
    onClose();
  }, [onClose]);

  return (
    <Modal
      visible={visible}
      animationType="slide"
      onRequestClose={handleClose}
      onShow={() => {
        hasScannedRef.current = false;
        setError(null);
      }}
    >
      <SafeAreaView className="flex-1 bg-black">
        <View className="flex-row items-center justify-between px-4 py-3">
          <Text className="font-semibold text-base text-white">
            Scan sign-in QR
          </Text>
          <TouchableOpacity onPress={handleClose} className="px-3 py-2">
            <Text className="font-medium text-base text-white">Close</Text>
          </TouchableOpacity>
        </View>

        <View className="flex-1">
          {!permission ? (
            <View className="flex-1 items-center justify-center">
              <ActivityIndicator color="#ffffff" />
            </View>
          ) : !permission.granted ? (
            <View className="flex-1 items-center justify-center px-6">
              <Text className="mb-4 text-center text-base text-white">
                PostHog needs camera access to scan the QR code shown on the web
                app.
              </Text>
              <TouchableOpacity
                className="rounded-lg bg-white px-5 py-3"
                onPress={requestPermission}
              >
                <Text className="font-semibold text-base text-black">
                  Grant camera access
                </Text>
              </TouchableOpacity>
            </View>
          ) : (
            <CameraView
              style={{ flex: 1 }}
              facing="back"
              barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
              onBarcodeScanned={handleBarcode}
            >
              <View className="flex-1 items-center justify-end px-6 pb-10">
                {error ? (
                  <View className="mb-3 rounded-lg bg-black/70 px-4 py-2">
                    <Text className="text-sm text-white">{error}</Text>
                  </View>
                ) : null}
                <Text className="rounded-lg bg-black/60 px-4 py-2 text-center text-sm text-white">
                  Point your camera at the QR code shown in the PostHog web app
                  after creating a personal API key.
                </Text>
              </View>
            </CameraView>
          )}
        </View>
      </SafeAreaView>
    </Modal>
  );
}
