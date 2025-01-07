class Libxmlsec1 < Formula
  desc "XML security library"
  homepage "https://www.aleksey.com/xmlsec/"
  url "https://www.aleksey.com/xmlsec/download/xmlsec1-1.2.37.tar.gz"
  sha256 "5f8dfbcb6d1e56bddd0b5ec2e00a3d0ca5342a9f57c24dffde5c796b2be2871c"
  license "MIT"

  livecheck do
    url "https://www.aleksey.com/xmlsec/download/"
    regex(/href=.*?xmlsec1[._-]v?(\d+(?:\.\d+)+)\.t/i)
  end

  bottle do
    sha256 cellar: :any,                 arm64_ventura:  "26d6ebddf4e97431819583ad699228360886d81786b332084693d0ad34aa2c72"
    sha256 cellar: :any,                 arm64_monterey: "66646e0a3c47fe21b5d6257d2940c1cbaddd68fd71845ae21eb34275b2913db4"
    sha256 cellar: :any,                 arm64_big_sur:  "6520bff7f714071fc7a5925dc2335c5482ce59383386500e1f51680bf3e69850"
    sha256 cellar: :any,                 ventura:        "15faa359429f324b4d18e49c70b0832cf93eb052ad0ef74ccddf1a2db0a4aad5"
    sha256 cellar: :any,                 monterey:       "dfc4528593b38556559a49053f7b5e3a46ae07d844ad3412a65c22214624a932"
    sha256 cellar: :any,                 big_sur:        "d428a24cc5c8165e84718292cd4a7a21519b1ce1f46c82ffff0bc27216b8a573"
    sha256 cellar: :any,                 catalina:       "b67b572409b3d79387f621c9f28338d0ec99342477f50643ff3a6032b58133c6"
    sha256 cellar: :any_skip_relocation, x86_64_linux:   "a52005111565d460c6774d5c5be9c8a0db05e0a06dc8715b7c1f59ab4a66fcb0"
  end

  depends_on "pkg-config" => :build
  depends_on "gnutls" # Yes, it wants both ssl/tls variations
  depends_on "libgcrypt"
  depends_on "libxml2"
  depends_on "openssl@3"
  uses_from_macos "libxslt"

  on_macos do
    depends_on xcode: :build
  end

  # Add HOMEBREW_PREFIX/lib to dl load path
  patch :DATA

  # Fix -flat_namespace being used on Big Sur and later.
  patch do
    url "https://raw.githubusercontent.com/Homebrew/formula-patches/03cf8088210822aa2c1ab544ed58ea04c897d9c4/libtool/configure-big_sur.diff"
    sha256 "35acd6aebc19843f1a2b3a63e880baceb0f5278ab1ace661e57a502d9d78c93c"
  end

  def install
    args = ["--disable-dependency-tracking",
            "--prefix=#{prefix}",
            "--disable-crypto-dl",
            "--disable-apps-crypto-dl",
            "--with-nss=no",
            "--with-nspr=no",
            "--enable-mscrypto=no",
            "--enable-mscng=no",
            "--with-openssl=#{Formula["openssl@1.1"].opt_prefix}"]

    system "./configure", *args
    system "make", "install"
  end

  test do
    system "#{bin}/xmlsec1", "--version"
    system "#{bin}/xmlsec1-config", "--version"
  end
end

__END__
diff --git a/src/dl.c b/src/dl.c
index 6e8a56a..0e7f06b 100644
--- a/src/dl.c
+++ b/src/dl.c
@@ -141,6 +141,7 @@ xmlSecCryptoDLLibraryCreate(const xmlChar* name) {
     }

 #ifdef XMLSEC_DL_LIBLTDL
+    lt_dlsetsearchpath("HOMEBREW_PREFIX/lib");
     lib->handle = lt_dlopenext((char*)lib->filename);
     if(lib->handle == NULL) {
         xmlSecError(XMLSEC_ERRORS_HERE,
