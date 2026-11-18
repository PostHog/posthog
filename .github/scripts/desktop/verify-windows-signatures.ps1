# Fails unless every Windows artifact carries a valid Authenticode signature
# whose subject satisfies the publisherName electron-builder wrote into
# app-update.yml, which is the value electron-updater enforces on updates.
param(
  [Parameter(Mandatory = $true)] [string] $OutDir
)
$ErrorActionPreference = "Stop"

$updateConfig = Join-Path $OutDir "win-unpacked/resources/app-update.yml"
$publisherLine = Select-String -LiteralPath $updateConfig -Pattern '^\s*-\s*["'']?(CN=.+?)["'']?\s*$' | Select-Object -First 1
if (-not $publisherLine) {
  throw "FAIL: no publisherName in $updateConfig, the build was packaged without Azure signing"
}
$expected = [System.Security.Cryptography.X509Certificates.X500DistinguishedName]::new($publisherLine.Matches[0].Groups[1].Value)
$expectedParts = $expected.Format($true).Trim() -split "\r?\n"

$files = @(Get-ChildItem -LiteralPath $OutDir -File -Filter "*.exe")
$files += Get-Item -LiteralPath (Join-Path $OutDir "win-unpacked/PostHog.exe")
foreach ($file in $files) {
  $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
  if ($signature.Status -ne "Valid") {
    throw "FAIL: $($file.Name) signature status is $($signature.Status)"
  }
  $actualParts = $signature.SignerCertificate.SubjectName.Format($true).Trim() -split "\r?\n"
  $missing = $expectedParts | Where-Object { $actualParts -notcontains $_ }
  if ($missing) {
    throw "FAIL: $($file.Name) is signed by '$($signature.SignerCertificate.Subject)', app-update.yml expects '$($expected.Name)'"
  }
  Write-Output "OK: $($file.Name) signed by $($signature.SignerCertificate.Subject)"
}
